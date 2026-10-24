// The starting-up popup for HEXBREACH: a small panel with a hex dump that
// fills in and a progress bar, on screen while Python and pygame load.
//
// run.sh starts it before anything else and gives the game a pipe to it. The
// game writes one line per step of its start, "55 opening display", and then
// "done" (startup.py). The popup never holds the game up, and takes no clicks
// and no keys. If the pipe closes with no "done", the game did not start, and
// the popup says so rather than fill its bar.
//
//   hexbreach-splash start|setup <game pid>   fed on stdin (setup: the first run's install)
//   hexbreach-splash demo                     plays by itself
//   hexbreach-splash check                    no window: prints what it reads (the tests)
//
// HEXBREACH_SPLASH_LOG=file logs when each thing happened. Build with build.sh.
import AppKit

// ---- the look: the game's own (ui.py, scenes.py)
func rgb(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> NSColor {
    return NSColor(srgbRed: r / 255, green: g / 255, blue: b / 255, alpha: 1)
}

let BLACK = rgb(0, 0, 0)
let GREEN = rgb(57, 255, 106)
let DIM = rgb(26, 122, 58)
let AMBER = rgb(255, 176, 0)
let RED = rgb(255, 64, 64)

let TITLE = "HEXBREACH"
let DUMP = Array("HEXBREACH v1.0\r\n".utf8)     // the 16 bytes that arrive as the bar fills
let COLS = 44, ROWS = 9                         // the popup, in characters
let BAR = 30                                    // the bar, in characters
let FONT_SIZE: CGFloat = 15

let MIN_VISIBLE = 1.0       // seconds the popup is up at the least, so a fast start still plays
let HOLD = 0.25             // seconds the full bar stays up
let FAIL_HOLD = 3.0         // seconds the failure line stays up
let QUIET = 30.0            // seconds without a word from the game before giving up
let SETUP_QUIET = 600.0     // the same, while the first run installs
let SPEED = 1.3             // the fastest the bar moves, in bars per second
let CREEP = 0.15            // how far the bar drifts past the last step while it waits for the next

// ---- the log
let born = Date()
let logFile: FileHandle? = {
    guard let path = ProcessInfo.processInfo.environment["HEXBREACH_SPLASH_LOG"] else { return nil }
    if !FileManager.default.fileExists(atPath: path) {
        FileManager.default.createFile(atPath: path, contents: nil)
    }
    let file = FileHandle(forWritingAtPath: path)
    file?.seekToEndOfFile()
    return file
}()

/// A line for the log: what happened, and how many seconds after the popup started.
func note(_ what: String) {
    logFile?.write(String(format: "%7.3f  %@\n", Date().timeIntervalSince(born), what).data(using: .utf8)!)
}

// ---- what the game says
enum Message {
    case step(Double, String)
    case done
}

/// One line from the game: "55 opening display" or "done". Anything else is nil.
func parse(_ line: String) -> Message? {
    if line == "done" { return .done }
    let parts = line.split(separator: " ", maxSplits: 1)
    guard let first = parts.first, let percent = Int(first), (0...100).contains(percent) else { return nil }
    return .step(Double(percent) / 100, parts.count > 1 ? String(parts[1]) : "")
}

/// How far along the start is, and how far along the bar shows it to be. The
/// bar moves smoothly to each step the game reports, then drifts on a little
/// so it never looks stuck. It never goes back, and is full only on "done".
struct Progress {
    enum Phase { case running, finishing, failed }
    var phase = Phase.running
    var steps: [(at: Double, label: String)]    // each step reported, and where on the bar it begins
    var reported = 0.0
    var shown = 0.0
    var fill = 0.0                              // finishing: bars per second

    init(first: String) {
        steps = [(0, first)]
    }

    /// The step the bar has reached, so on a fast start the labels keep pace with it.
    var label: String {
        if phase == .failed { return "start failed" }
        if shown >= 1 { return "ready" }
        return steps.last(where: { $0.at <= shown })?.label ?? ""
    }

    mutating func take(_ message: Message, elapsed: Double) {
        guard phase == .running else { return }
        switch message {
        case .step(let at, let label):
            reported = max(reported, min(at, 0.99))
            steps.append((reported, label))
        case .done:
            phase = .finishing
            fill = (1 - shown) / max(0.2, MIN_VISIBLE - HOLD - elapsed)
        }
    }

    mutating func advance(_ dt: Double) {
        switch phase {
        case .running:
            if shown < reported {
                shown = min(reported, shown + SPEED * dt)
            } else {
                shown += max(0, min(0.99, reported + CREEP) - shown) * 0.3 * dt
            }
        case .finishing:
            shown = min(1, shown + fill * dt)
        case .failed:
            break
        }
    }
}

// ---- the popup
final class SplashPanel: NSPanel {
    // never the window that takes the keys: those are the game's
    override var canBecomeKey: Bool { return false }
    override var canBecomeMain: Bool { return false }
}

/// Draws the popup on a grid of characters, as the game draws its screens.
final class SplashView: NSView {
    var progress: Progress
    let font: NSFont
    let cw: CGFloat, lh: CGFloat        // one character's width, one line's height

    init(progress: Progress, font: NSFont) {
        self.progress = progress
        self.font = font
        cw = ("0" as NSString).size(withAttributes: [.font: font]).width
        lh = ceil(font.ascender - font.descender) + 4
        super.init(frame: NSRect(x: 0, y: 0, width: ceil(CGFloat(COLS) * cw), height: CGFloat(ROWS) * lh))
    }

    required init?(coder: NSCoder) {
        fatalError("not used")
    }

    override var isFlipped: Bool { return true }

    func put(_ s: String, _ col: Int, _ row: Int, _ color: NSColor, on background: NSColor? = nil) {
        let cell = NSRect(x: CGFloat(col) * cw, y: CGFloat(row) * lh, width: CGFloat(s.count) * cw, height: lh)
        if let background = background {
            background.setFill()
            cell.fill()
        }
        let drop = (lh - (font.ascender - font.descender)) / 2
        (s as NSString).draw(at: NSPoint(x: cell.minX, y: cell.minY + drop),
                             withAttributes: [.font: font, .foregroundColor: color])
    }

    override func draw(_ dirtyRect: NSRect) {
        BLACK.setFill()
        bounds.fill()
        // the outline runs through the middle of the outer characters, and the title sits on it
        GREEN.setStroke()
        NSBezierPath(rect: bounds.insetBy(dx: (cw / 2).rounded() + 0.5, dy: (lh / 2).rounded() + 0.5)).stroke()
        put(" \(TITLE) ", 2, 0, AMBER, on: BLACK)

        // the dump: offset, 8 bytes, ASCII. A byte not yet arrived is ??, as a lost one is in the game
        let arrived = Int(progress.shown * Double(DUMP.count))
        for row in 0 ..< DUMP.count / 8 {
            put(String(format: "%04X", row * 8), 3, 2 + row, DIM)
            for k in 0 ..< 8 {
                let i = row * 8 + k, byte = DUMP[i]
                let here = i < arrived, text = here && (32 ..< 127).contains(byte)
                put(here ? String(format: "%02X", byte) : "??", 9 + 3 * k, 2 + row, here ? GREEN : DIM)
                put(text ? String(Character(UnicodeScalar(byte))) : ".", 34 + k, 2 + row, text ? GREEN : DIM)
            }
        }

        let failed = progress.phase == .failed
        put(progress.label, 3, 5, failed ? RED : GREEN)
        let n = Int(progress.shown * Double(BAR))
        let bar = "[" + String(repeating: "|", count: n) + String(repeating: " ", count: BAR - n) + "]"
        put(bar + String(format: " %3d%%", Int(progress.shown * 100)), 3, 6, failed ? DIM : GREEN)
    }
}

final class Splash: NSObject {
    let setup: Bool                 // the first run: the install comes before the game says anything
    var progress: Progress
    let view: SplashView
    let panel: SplashPanel
    var lastTick = Date()
    var lastWord = Date()
    var heard = false               // the game has sent its first line
    var fullAt: Date?               // when the bar filled
    var failedAt: Date?
    var seen = false                // the popup has been on screen
    var input: DispatchSourceRead?
    var game: DispatchSourceProcess?
    var unread = Data()

    init(setup: Bool, screen: NSScreen) {
        self.setup = setup
        progress = Progress(first: setup ? "first-time setup" : "starting")
        let font = NSFont(name: "Menlo-Regular", size: FONT_SIZE)
            ?? NSFont.monospacedSystemFont(ofSize: FONT_SIZE, weight: .regular)
        view = SplashView(progress: progress, font: font)
        let size = view.frame.size, on = screen.visibleFrame
        let rect = NSRect(x: (on.midX - size.width / 2).rounded(), y: (on.midY - size.height / 2).rounded(),
                          width: size.width, height: size.height)
        // A panel that floats over everything, a fullscreen app included,
        // without ever becoming the app in front: the keys and the clicks stay
        // with whatever has them. Every line here is needed for that.
        panel = SplashPanel(contentRect: rect, styleMask: [.borderless, .nonactivatingPanel],
                            backing: .buffered, defer: false)
        panel.level = .statusBar
        panel.collectionBehavior = [.canJoinAllSpaces, .fullScreenAuxiliary, .stationary, .ignoresCycle]
        panel.hidesOnDeactivate = false
        panel.ignoresMouseEvents = true
        panel.animationBehavior = .none
        panel.isOpaque = true
        panel.hasShadow = false
        panel.backgroundColor = BLACK
        panel.contentView = view
        super.init()
        // If macOS takes the popup off screen (it does as a window slides to
        // fullscreen), it goes for good: better gone early than back with a flicker.
        NotificationCenter.default.addObserver(self, selector: #selector(occluded),
                                               name: NSWindow.didChangeOcclusionStateNotification, object: panel)
    }

    func show() {
        panel.orderFrontRegardless()
        note("shown")
        let timer = Timer(timeInterval: 1.0 / 30, target: self, selector: #selector(tick), userInfo: nil, repeats: true)
        RunLoop.main.add(timer, forMode: .common)
    }

    /// Read the game's lines from stdin, and watch the game itself.
    func listen(game pid: pid_t) {
        _ = fcntl(0, F_SETFL, fcntl(0, F_GETFL) | O_NONBLOCK)
        let source = DispatchSource.makeReadSource(fileDescriptor: 0, queue: .main)
        source.setEventHandler { [unowned self] in self.read() }
        source.resume()
        input = source
        if pid > 0 {
            let watch = DispatchSource.makeProcessSource(identifier: pid, eventMask: .exit, queue: .main)
            watch.setEventHandler { [unowned self] in self.gone("the game exited") }
            watch.resume()
            game = watch
        }
    }

    /// A start played from a script, to see the popup with no game.
    func demo() {
        let script = [(0.5, "20 loading engine"), (1.5, "55 opening display"), (2.2, "70 opening window"),
                      (3.0, "95 drawing title"), (3.4, "done")]
        for (after, line) in script {
            DispatchQueue.main.asyncAfter(deadline: .now() + after) { [unowned self] in
                if let message = parse(line) { self.take(message) }
            }
        }
    }

    func read() {
        var buffer = [UInt8](repeating: 0, count: 4096)
        var closed = false
        while true {
            let n = Darwin.read(0, &buffer, buffer.count)
            if n > 0 {
                unread.append(contentsOf: buffer[0 ..< n])
                continue
            }
            closed = n == 0         // otherwise: nothing more for now
            break
        }
        while let end = unread.firstIndex(of: 0x0A) {
            let line = String(decoding: unread[unread.startIndex ..< end], as: UTF8.self)
            unread.removeSubrange(unread.startIndex ... end)
            if let message = parse(line) { take(message) }
        }
        if closed {
            input?.cancel()         // a closed pipe reads as ready for ever
            input = nil
            gone("the pipe closed")
        }
    }

    func take(_ message: Message) {
        heard = true
        lastWord = Date()
        progress.take(message, elapsed: Date().timeIntervalSince(born))
        switch message {
        case .step(let at, let label): note("step \(Int((at * 100).rounded())) \(label)")
        case .done: note("done")
        }
    }

    /// The game closed the pipe or exited. With no "done" first, it never drew a frame.
    func gone(_ why: String) {
        guard progress.phase == .running else { return }
        note("game gone: " + why)
        progress.phase = .failed
        failedAt = Date()
    }

    func leave(_ why: String, code: Int32 = 0) -> Never {
        note("exit: " + why)
        exit(code)
    }

    @objc func occluded() {
        let visible = panel.occlusionState.contains(.visible)
        note(visible ? "visible" : "hidden")
        if visible {
            seen = true
        } else if seen {
            leave("taken off screen")
        }
    }

    @objc func tick() {
        let now = Date()
        progress.advance(min(now.timeIntervalSince(lastTick), 0.1))
        lastTick = now
        switch progress.phase {
        case .running:
            if now.timeIntervalSince(lastWord) > (setup && !heard ? SETUP_QUIET : QUIET) {
                leave("no word from the game")
            }
        case .finishing:
            if progress.shown >= 1 {
                let since = fullAt ?? now
                fullAt = since
                if now.timeIntervalSince(since) >= HOLD { leave("done") }
            }
        case .failed:
            if now.timeIntervalSince(failedAt ?? now) >= FAIL_HOLD { leave("the game did not start", code: 1) }
        }
        view.progress = progress
        view.needsDisplay = true
    }
}

// ---- start
let arguments = CommandLine.arguments
let mode = arguments.count > 1 ? arguments[1] : "demo"

if mode == "check" {
    var finished = false
    while let line = readLine() {
        switch parse(line) {
        case .step(let at, let label)?: print(Int((at * 100).rounded()), label)
        case .done?: print("done"); finished = true
        case nil: break
        }
    }
    exit(finished ? 0 : 1)
}

let app = NSApplication.shared
app.setActivationPolicy(.accessory)     // no Dock icon, and never the app in front
guard let screen = NSScreen.screens.first else { exit(0) }
let splash = Splash(setup: mode == "setup", screen: screen)
splash.show()
if mode == "demo" {
    splash.demo()
} else {
    splash.listen(game: arguments.count > 2 ? pid_t(arguments[2]) ?? 0 : 0)
}
app.run()
