# Accessibility flag measurement

Throwaway prototype for issue #3. Records, every few seconds, how much text the frontmost window exposes, how long reading it takes, and how much CPU the app's processes use, with Chrome/Electron's accessibility flag off and then on. Results hold app names, sizes and timings only; window text is recorded only with `--samples`.

```bash
swiftc -O measure.swift -o measure
./measure --mode off --minutes 5
# quit and reopen nothing; continue straight into
./measure --mode on --minutes 5
python3 summarize.py results/off.jsonl results/on.jsonl
```

Run the `off` pass first: once set, the flag stays on in each app until it is quit and reopened. Quit and reopen Chrome and Electron apps afterwards to restore them.
