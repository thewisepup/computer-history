---------------------------- MODULE SpoolHandoff ----------------------------
(* The spool handoff between the capture agent and ingest.                  *)
(*                                                                          *)
(* The agent (capture-agent/Sources/CaptureAgent/SpoolWriter.swift) appends *)
(* records to open.part and renames it to a finished <stamp>.jsonl file.    *)
(* Ingest (computer_history/sources/ax_text/adapter.py, spool.py) reads    *)
(* the same files once per stream (ax-text, screenshot): it lists them,     *)
(* reads the oldest, commits that stream's records, and once both streams   *)
(* stored that same file, removes it or sets it aside into unreadable/.     *)
(* Either side can crash between any two steps, and several ingests can    *)
(* run at once.                                                             *)
(*                                                                          *)
(* A file name is a whole number standing for its millisecond stamp.        *)
(* A file's content is the set of record ids on its lines; order and line   *)
(* bytes do not matter to the property. A file's generation stands for what *)
(* read_file tells it apart by (device, inode, size, mtime).                *)

EXTENDS Naturals, FiniteSets, Sequences

CONSTANTS
    Records,          \* record ids the agent will try to capture
    Screenshots,      \* the records that are screenshot records; the rest are ax-text
    Ingests,          \* concurrent ingest processes (watch, one-off ingest)
    MaxClock,         \* the wall clock runs over 0..MaxClock
    ClockStepsBack,   \* TRUE: the wall clock can be set back (NTP, the user)
    MaxAgentCrashes,
    MaxIngestCrashes

(* Stamps start at 1, so the fresh agent's lastFinished of 0 (the epoch)   *)
(* is behind every clock reading, as it is for a real clock.                *)
Names == 1 .. (MaxClock + Cardinality(Records) + MaxAgentCrashes + 1)

Streams == {"ax-text", "screenshot"}
StreamOf(r) == IF r \in Screenshots THEN "screenshot" ELSE "ax-text"

VARIABLES
    (* the agent process: SpoolWriter *)
    agentUp,      \* holds agent.lock and runs
    lastFinished, \* SpoolWriter.lastFinished, lost on a crash
    openPart,     \* records on complete lines of open.part
    unwritten,    \* records not yet appended
    acked,        \* records whose append returned
    clock,        \* the wall clock, SpoolTime(now())
    used,         \* every name the agent has finished a file to (a ghost)
    agentCrashes,
    (* the spool folder *)
    present,      \* finished file names in the spool folder
    content,      \* name -> the records the file at that name holds
    gen,          \* name -> how many files have been finished to that name
    unusable,     \* names whose file holds a line parse_record rejects
    aside,        \* records that reached unreadable/
    (* each ingest process: one CaptureSpool and its connection *)
    pc,           \* "idle" | "read" | "committed" | "linked"
    listed,       \* stream -> CaptureSpool._listed[stream], oldest first
    stored,       \* CaptureSpool._stored: <<name, generation, stream>> committed here
    readStream,   \* the stream the pull is for
    readPath,     \* the path the pull read, bound into its after-commit step
    readGen,      \* the generation of the file the pull read
    readRecs,     \* the records the pull read from that file
    readGone,     \* the head file was missing when read (FileNotFoundError)
    readUnusable, \* the head file had an unusable line
    ingestCrashes,
    (* the database *)
    db            \* record ids in observations (UNIQUE (source, source_id))

agentVars  == <<agentUp, lastFinished, openPart, unwritten, acked, clock, used,
                agentCrashes>>
folderVars == <<present, content, gen, unusable, aside>>
ingestVars == <<pc, listed, stored, readStream, readPath, readGen, readRecs, readGone,
                readUnusable, ingestCrashes>>
vars == <<agentVars, folderVars, ingestVars, db>>

Max(S) == CHOOSE x \in S : \A y \in S : y <= x
Min(S) == CHOOSE x \in S : \A y \in S : x <= y

RECURSIVE SortedSeq(_)
SortedSeq(S) == IF S = {} THEN << >>
                ELSE <<Min(S)>> \o SortedSeq(S \ {Min(S)})

Init ==
    /\ agentUp = FALSE
    /\ lastFinished = 0
    /\ openPart = {}
    /\ unwritten = Records
    /\ acked = {}
    /\ clock = 1
    /\ used = {}
    /\ agentCrashes = 0
    /\ present = {}
    /\ content = [n \in Names |-> {}]
    /\ gen = [n \in Names |-> 0]
    /\ unusable = {}
    /\ aside = {}
    /\ pc = [i \in Ingests |-> "idle"]
    /\ listed = [i \in Ingests |-> [s \in Streams |-> << >>]]
    /\ stored = [i \in Ingests |-> {}]
    /\ readStream = [i \in Ingests |-> "ax-text"]
    /\ readPath = [i \in Ingests |-> 1]
    /\ readGen = [i \in Ingests |-> 0]
    /\ readRecs = [i \in Ingests |-> {}]
    /\ readGone = [i \in Ingests |-> FALSE]
    /\ readUnusable = [i \in Ingests |-> FALSE]
    /\ ingestCrashes = [i \in Ingests |-> 0]
    /\ db = {}

-----------------------------------------------------------------------------
(* The agent *)

(* SpoolWriter.startIfNeeded: take agent.lock, then lastFinished is the     *)
(* newest finished name in the folder (the fresh process starts from 0).    *)
AgentStarts ==
    /\ ~agentUp
    /\ agentUp' = TRUE
    /\ lastFinished' = IF present = {} THEN 0 ELSE Max(present)
    /\ UNCHANGED <<openPart, unwritten, acked, clock, used, agentCrashes, folderVars,
                   ingestVars, db>>

(* SpoolWriter.append: one line written and the call returns. A torn tail  *)
(* left by an earlier failed write is dropped first, and a torn line never  *)
(* counts as a record, so torn lines are not modeled.                       *)
AgentAppends ==
    /\ agentUp
    /\ \E r \in unwritten :
        /\ openPart' = openPart \cup {r}
        /\ unwritten' = unwritten \ {r}
        /\ acked' = acked \cup {r}
    /\ UNCHANGED <<agentUp, lastFinished, clock, used, agentCrashes, folderVars, ingestVars, db>>

(* SpoolWriter.finishLocked: a non-empty open.part is renamed with          *)
(* RENAME_EXCL to the first free stamp at or after                          *)
(* max(now, lastFinished + 1). The file may hold a line ingest rejects      *)
(* (a format it does not know); the agent itself never writes one, so this *)
(* stands in for any such line.                                             *)
AgentFinishes ==
    /\ agentUp
    /\ openPart # {}
    /\ LET from == IF clock > lastFinished THEN clock ELSE lastFinished + 1
           n == Min({m \in Names : m >= from /\ m \notin present})
       IN /\ present' = present \cup {n}
          /\ content' = [content EXCEPT ![n] = openPart]
          /\ gen' = [gen EXCEPT ![n] = gen[n] + 1]
          /\ \E bad \in BOOLEAN :
                unusable' = IF bad THEN unusable \cup {n} ELSE unusable \ {n}
          /\ lastFinished' = n
          /\ used' = used \cup {n}
    /\ openPart' = {}
    /\ UNCHANGED <<agentUp, unwritten, acked, clock, agentCrashes, aside, ingestVars,
                   db>>

(* A crash or kill: open.part stays on disk, lastFinished is lost. launchd *)
(* restarts the agent seconds later, longer than names ever run ahead of    *)
(* the clock (two finishes in one millisecond), so a steady clock is past   *)
(* every name used before the restart.                                      *)
AgentCrashes ==
    /\ agentUp
    /\ agentCrashes < MaxAgentCrashes
    /\ agentUp' = FALSE
    /\ lastFinished' = 0
    /\ agentCrashes' = agentCrashes + 1
    /\ clock' = Max(used \cup {clock}) + 1
    /\ UNCHANGED <<openPart, unwritten, acked, used, folderVars, ingestVars, db>>

ClockTicks ==
    /\ clock < MaxClock
    /\ clock' = clock + 1
    /\ UNCHANGED <<agentUp, lastFinished, openPart, unwritten, acked, used, agentCrashes,
                   folderVars, ingestVars, db>>

ClockStepsBackward ==
    /\ ClockStepsBack
    /\ clock > 1
    /\ \E c \in 1 .. (clock - 1) : clock' = c
    /\ UNCHANGED <<agentUp, lastFinished, openPart, unwritten, acked, used, agentCrashes,
                   folderVars, ingestVars, db>>

-----------------------------------------------------------------------------
(* Ingest, one CaptureSpool per process *)

(* CaptureSpool.pull_after for a stream with nothing listed for it:       *)
(* finished_files, oldest first by name, and _forget_all_but drops what it  *)
(* stored of files no longer present.                                       *)
IngestLists(i, s) ==
    /\ pc[i] = "idle"
    /\ listed[i][s] = << >>
    /\ present # {}
    /\ listed' = [listed EXCEPT ![i][s] = SortedSeq(present)]
    /\ stored' = [stored EXCEPT ![i] = {e \in stored[i] : e[1] \in present}]
    /\ UNCHANGED <<agentVars, folderVars, pc, readStream, readPath, readGen, readRecs, readGone,
                   readUnusable, ingestCrashes, db>>

(* pull_after reads the head of the stream's listed files: read_file keeps  *)
(* the stream's records and what tells the file apart, or FileNotFoundError *)
(* when another process removed it.                                         *)
IngestReads(i, s) ==
    /\ pc[i] = "idle"
    /\ listed[i][s] # << >>
    /\ LET path == Head(listed[i][s]) IN
        /\ readStream' = [readStream EXCEPT ![i] = s]
        /\ readPath' = [readPath EXCEPT ![i] = path]
        /\ readGen' = [readGen EXCEPT ![i] = gen[path]]
        /\ readGone' = [readGone EXCEPT ![i] = path \notin present]
        /\ readRecs' = [readRecs EXCEPT ![i] =
                          IF path \in present THEN {r \in content[path] : StreamOf(r) = s}
                          ELSE {}]
        /\ readUnusable' = [readUnusable EXCEPT ![i] = path \in present /\ path \in unusable]
    /\ pc' = [pc EXCEPT ![i] = "read"]
    /\ UNCHANGED <<agentVars, folderVars, listed, stored, ingestCrashes, db>>

(* commit_pull -> insert_observations: one transaction, ON CONFLICT DO      *)
(* NOTHING on (source, source_id).                                          *)
IngestCommits(i) ==
    /\ pc[i] = "read"
    /\ db' = db \cup readRecs[i]
    /\ pc' = [pc EXCEPT ![i] = "committed"]
    /\ UNCHANGED <<agentVars, folderVars, listed, stored, readStream, readPath, readGen, readRecs,
                   readGone, readUnusable, ingestCrashes>>

(* The after-commit step: take the path off the stream's listed files and  *)
(* mark that stream stored this file (_stored_by). Only when every stream  *)
(* has stored the same file does it run remove_finished (unlink,           *)
(* missing_ok) or set_aside; a missing file is only dropped (_drop).       *)
(* unlink and link act on whatever file has that name now.                  *)
IngestFinishes(i) ==
    /\ pc[i] = "committed"
    /\ LET path == readPath[i]
           s == readStream[i]
           done == stored[i] \cup {<<path, readGen[i], s>>}
           complete == \A t \in Streams : <<path, readGen[i], t>> \in done
       IN
        IF readGone[i] THEN
            /\ pc' = [pc EXCEPT ![i] = "idle"]
            /\ UNCHANGED <<folderVars, stored>>
        ELSE IF ~complete THEN
            /\ stored' = [stored EXCEPT ![i] = done]
            /\ pc' = [pc EXCEPT ![i] = "idle"]
            /\ UNCHANGED <<folderVars>>
        ELSE
            /\ stored' = [stored EXCEPT ![i] =
                            {e \in done : ~(e[1] = path /\ e[2] = readGen[i])}]
            /\ IF ~readUnusable[i] THEN
                   /\ present' = present \ {path}
                   /\ pc' = [pc EXCEPT ![i] = "idle"]
                   /\ UNCHANGED <<content, gen, unusable, aside>>
               ELSE
                   (* set_aside: os.link(path, unreadable/<name>) *)
                   /\ aside' = IF path \in present THEN aside \cup content[path] ELSE aside
                   /\ pc' = [pc EXCEPT ![i] = "linked"]
                   /\ UNCHANGED <<present, content, gen, unusable>>
    /\ listed' = [listed EXCEPT ![i][readStream[i]] = Tail(listed[i][readStream[i]])]
    /\ UNCHANGED <<agentVars, readStream, readPath, readGen, readRecs, readGone, readUnusable,
                   ingestCrashes, db>>

(* set_aside, second half: path.unlink(missing_ok=True). The head is       *)
(* already off the listed files, so the path is the one just linked.        *)
IngestUnlinksAside(i) ==
    /\ pc[i] = "linked"
    /\ present' = present \ {readPath[i]}
    /\ pc' = [pc EXCEPT ![i] = "idle"]
    /\ UNCHANGED <<agentVars, content, gen, unusable, aside, listed, stored, readStream, readPath,
                   readGen, readRecs, readGone, readUnusable, ingestCrashes, db>>

(* A crash or Ctrl-C: the transaction either committed or rolled back, and *)
(* the new process starts with nothing listed and nothing marked stored.   *)
IngestCrashes(i) ==
    /\ ingestCrashes[i] < MaxIngestCrashes
    /\ pc' = [pc EXCEPT ![i] = "idle"]
    /\ listed' = [listed EXCEPT ![i] = [s \in Streams |-> << >>]]
    /\ stored' = [stored EXCEPT ![i] = {}]
    /\ ingestCrashes' = [ingestCrashes EXCEPT ![i] = ingestCrashes[i] + 1]
    /\ UNCHANGED <<agentVars, folderVars, readStream, readPath, readGen, readRecs, readGone,
                   readUnusable, db>>

(* Every record is appended, every file finished and drained: nothing left *)
(* to do.                                                                   *)
Done ==
    /\ unwritten = {}
    /\ openPart = {}
    /\ present = {}
    /\ \A i \in Ingests : pc[i] = "idle"
    /\ UNCHANGED vars

Next ==
    \/ AgentStarts \/ AgentAppends \/ AgentFinishes \/ AgentCrashes
    \/ ClockTicks \/ ClockStepsBackward
    \/ \E i \in Ingests :
        \/ \E s \in Streams : IngestLists(i, s) \/ IngestReads(i, s)
        \/ IngestCommits(i)
        \/ IngestFinishes(i) \/ IngestUnlinksAside(i) \/ IngestCrashes(i)
    \/ Done

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Properties *)

TypeOK ==
    /\ agentUp \in BOOLEAN
    /\ lastFinished \in Names \cup {0}
    /\ clock \in Names
    /\ openPart \subseteq Records
    /\ present \subseteq Names
    /\ \A i \in Ingests : pc[i] \in {"idle", "read", "committed", "linked"}
    /\ Screenshots \subseteq Records

(* Every record whose append returned is stored, or still in the spool for *)
(* ingest to read: in open.part or in a finished file. A record that only  *)
(* reached unreadable/ is never read again, so it does not count.          *)
NoLoss ==
    \A r \in acked :
        \/ r \in db
        \/ r \in openPart
        \/ \E n \in present : r \in content[n]

=============================================================================
