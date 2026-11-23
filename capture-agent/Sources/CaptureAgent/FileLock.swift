import Darwin
import Foundation

struct LockHeld: Error {}

/// Opens the file, creating it with the mode, and locks it without waiting, returning its descriptor.
func lockExclusively(_ path: String, mode: mode_t) throws -> Int32 {
    let descriptor = open(path, O_RDWR | O_CREAT | O_CLOEXEC, mode)
    guard descriptor >= 0 else { throw posixError() }
    guard flock(descriptor, LOCK_EX | LOCK_NB) == 0 else {
        let error: any Error = errno == EWOULDBLOCK ? LockHeld() : posixError()
        close(descriptor)
        throw error
    }
    return descriptor
}

func posixError() -> POSIXError {
    POSIXError(POSIXErrorCode(rawValue: errno) ?? .EIO)
}
