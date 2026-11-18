import AppKit
import ApplicationServices
import Darwin

struct Options {
    var mode = "off"
    var minutes = 5.0
    var interval = 5.0
    var out = ""
    var samples = false
}

func parseOptions() -> Options {
    var o = Options()
    var args = CommandLine.arguments.dropFirst().makeIterator()
    while let a = args.next() {
        switch a {
        case "--mode": o.mode = args.next() ?? "off"
        case "--minutes": o.minutes = Double(args.next() ?? "") ?? 5
        case "--interval": o.interval = Double(args.next() ?? "") ?? 5
        case "--out": o.out = args.next() ?? ""
        case "--samples": o.samples = true
        default:
            print("usage: measure --mode off|on [--minutes 5] [--interval 5] [--out file] [--samples]")
            exit(2)
        }
    }
    guard o.mode == "off" || o.mode == "on" else { print("--mode must be off or on"); exit(2) }
    if o.out.isEmpty { o.out = "results/\(o.mode).jsonl" }
    return o
}

let perCallTimeout: Float = 0.25
let agentBudget = 2.0
let measureBudget = 10.0
let capBytes = 50_000
let maxElements = 30_000

func copyAttr(_ el: AXUIElement, _ name: String) -> (CFTypeRef?, AXError) {
    var v: CFTypeRef?
    let e = AXUIElementCopyAttributeValue(el, name as CFString, &v)
    return (v, e)
}

struct WalkResult {
    var elements = 0
    var bytesTotal = 0
    var bytesAt2s = 0
    var finishedWithin2s = false
    var finished = false
    var walkMs = 0.0
    var timeouts = 0
    var errors = 0
    var secureSkipped = 0
    var bytesByRole: [String: Int] = [:]
    var samples: [String: String] = [:]
}

func walk(window: AXUIElement, keepSamples: Bool) -> WalkResult {
    var r = WalkResult()
    let start = Date()
    var stack = [window]
    func note(_ e: AXError) {
        if e == .cannotComplete { r.timeouts += 1 } else if e != .success && e != .noValue && e != .attributeUnsupported { r.errors += 1 }
    }
    while let el = stack.popLast() {
        let elapsed = Date().timeIntervalSince(start)
        if elapsed > agentBudget && r.bytesAt2s == 0 && !r.finishedWithin2s { r.bytesAt2s = max(r.bytesTotal, 1) }
        if elapsed > measureBudget || r.elements >= maxElements { break }
        r.elements += 1
        let (roleV, roleE) = copyAttr(el, kAXRoleAttribute)
        note(roleE)
        let role = (roleV as? String) ?? "?"
        let subrole = (copyAttr(el, kAXSubroleAttribute).0 as? String) ?? ""
        if role == "AXSecureTextField" || subrole == "AXSecureTextField" { r.secureSkipped += 1; continue }
        for name in [kAXValueAttribute, kAXTitleAttribute, kAXDescriptionAttribute] {
            let (v, e) = copyAttr(el, name)
            note(e)
            guard let s = v as? String, !s.isEmpty else { continue }
            let n = s.utf8.count
            r.bytesTotal += n
            r.bytesByRole[role, default: 0] += n
            if keepSamples, r.samples[role] == nil { r.samples[role] = String(s.prefix(160)) }
        }
        let (kids, kidsE) = copyAttr(el, kAXChildrenAttribute)
        note(kidsE)
        if let arr = kids as? [AXUIElement] { stack.append(contentsOf: arr.reversed()) }
    }
    r.finished = stack.isEmpty
    r.walkMs = Date().timeIntervalSince(start) * 1000
    if r.finished && r.walkMs <= agentBudget * 1000 { r.finishedWithin2s = true; r.bytesAt2s = r.bytesTotal }
    if r.bytesAt2s == 0 { r.bytesAt2s = r.bytesTotal }
    return r
}

var timebase = mach_timebase_info_data_t()
mach_timebase_info(&timebase)

func cpuNanos(underPath prefix: String) -> UInt64 {
    let count = proc_listallpids(nil, 0)
    guard count > 0 else { return 0 }
    var pids = [pid_t](repeating: 0, count: Int(count) * 2)
    let got = proc_listallpids(&pids, Int32(pids.count * MemoryLayout<pid_t>.size))
    var total: UInt64 = 0
    var pathBuf = [CChar](repeating: 0, count: 4096)
    for pid in pids.prefix(Int(got)) where pid > 0 {
        guard proc_pidpath(pid, &pathBuf, UInt32(pathBuf.count)) > 0 else { continue }
        guard String(cString: pathBuf).hasPrefix(prefix) else { continue }
        var info = rusage_info_v2()
        let ok = withUnsafeMutablePointer(to: &info) {
            $0.withMemoryRebound(to: rusage_info_t?.self, capacity: 1) { proc_pid_rusage(pid, RUSAGE_INFO_V2, $0) }
        }
        guard ok == 0 else { continue }
        total += (info.ri_user_time + info.ri_system_time) * UInt64(timebase.numer) / UInt64(timebase.denom)
    }
    return total
}

func isChromiumFamily(_ app: NSRunningApplication) -> Bool {
    guard let url = app.bundleURL else { return false }
    let fm = FileManager.default
    if fm.fileExists(atPath: url.appendingPathComponent("Contents/Frameworks/Electron Framework.framework").path) { return true }
    let ids = ["com.google.Chrome", "com.google.Chrome.canary", "com.brave.Browser", "com.microsoft.edgemac", "company.thebrowser.Browser", "com.vivaldi.Vivaldi", "org.chromium.Chromium"]
    return ids.contains(app.bundleIdentifier ?? "")
}

let o = parseOptions()
guard AXIsProcessTrusted() else {
    print("This terminal has no Accessibility permission.")
    print("System Settings > Privacy & Security > Accessibility: turn on the app you are running this from, then restart it.")
    exit(1)
}
AXUIElementSetMessagingTimeout(AXUIElementCreateSystemWide(), perCallTimeout)

FileManager.default.createFile(atPath: o.out, contents: nil)
guard let handle = FileHandle(forWritingAtPath: o.out) else { print("cannot write \(o.out)"); exit(1) }

var flagResults: [pid_t: [String: String]] = [:]
var lastCPU: [String: (nanos: UInt64, at: Date)] = [:]
let iso = ISO8601DateFormatter()
let deadline = Date().addingTimeInterval(o.minutes * 60)
print("mode \(o.mode): sampling the frontmost window every \(Int(o.interval))s for \(o.minutes) min into \(o.out). Use your apps normally.")
if o.mode == "on" { print("The flag stays on in each app until you quit and reopen it.") }

while Date() < deadline {
    let tickStart = Date()
    autoreleasepool {
        guard let app = NSWorkspace.shared.frontmostApplication else { return }
        let pid = app.processIdentifier
        let appEl = AXUIElementCreateApplication(pid)
        AXUIElementSetMessagingTimeout(appEl, perCallTimeout)
        let chromium = isChromiumFamily(app)
        let alreadyOn = (copyAttr(appEl, "AXManualAccessibility").0 as? Bool) ?? false
        if o.mode == "on", chromium, flagResults[pid] == nil {
            var res: [String: String] = [:]
            for name in ["AXManualAccessibility", "AXEnhancedUserInterface"] {
                let e = AXUIElementSetAttributeValue(appEl, name as CFString, kCFBooleanTrue)
                res[name] = e == .success ? "set" : "error \(e.rawValue)"
            }
            flagResults[pid] = res
            Thread.sleep(forTimeInterval: 1.5)
        }
        let (winV, winE) = copyAttr(appEl, kAXFocusedWindowAttribute)
        var record: [String: Any] = [
            "at": iso.string(from: Date()), "mode": o.mode,
            "app": app.localizedName ?? "?", "bundleId": app.bundleIdentifier ?? "?",
            "chromium": chromium, "flagAlreadyOn": alreadyOn,
        ]
        if let res = flagResults[pid] { record["flag"] = res }
        if let path = app.bundleURL?.path {
            let now = Date(), nanos = cpuNanos(underPath: path)
            if let prev = lastCPU[path] {
                let wall = now.timeIntervalSince(prev.at) * 1e9
                if wall > 0, nanos >= prev.nanos { record["cpuPercent"] = Double(nanos - prev.nanos) / wall * 100 }
            }
            lastCPU[path] = (nanos, now)
        }
        if let win = winV, winE == .success, CFGetTypeID(win) == AXUIElementGetTypeID() {
            let w = walk(window: win as! AXUIElement, keepSamples: o.samples)
            record["elements"] = w.elements
            record["bytesTotal"] = w.bytesTotal
            record["bytesAt2s"] = w.bytesAt2s
            record["finished"] = w.finished
            record["finishedWithin2s"] = w.finishedWithin2s
            record["walkMs"] = (w.walkMs * 10).rounded() / 10
            record["timeouts"] = w.timeouts
            record["errors"] = w.errors
            record["secureSkipped"] = w.secureSkipped
            record["over50KB"] = w.bytesTotal > capBytes
            record["bytesByRole"] = w.bytesByRole
            if o.samples { record["samples"] = w.samples }
        } else {
            record["noWindow"] = winE == .cannotComplete ? "timeout" : "error \(winE.rawValue)"
        }
        if let data = try? JSONSerialization.data(withJSONObject: record, options: [.sortedKeys]) {
            handle.write(data)
            handle.write("\n".data(using: .utf8)!)
        }
        let kb = (record["bytesTotal"] as? Int ?? 0) / 1000
        let ms = record["walkMs"] as? Double ?? 0
        print("\(record["app"]!): \(kb) KB in \(Int(ms)) ms")
    }
    let rest = o.interval - Date().timeIntervalSince(tickStart)
    if rest > 0 { Thread.sleep(forTimeInterval: rest) }
}
try? handle.close()
print("done: \(o.out)")
