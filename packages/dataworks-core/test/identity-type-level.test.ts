/**
 * Type-level test: UserID must not be assignable from a plain string.
 * This verifies that Schema.brand creates a true nominal/opaque type.
 *
 * RED: This file should produce a TS compilation error if UserID is truly branded.
 * GREEN: If this file compiles without error, the brand is broken.
 */
import type { UserID } from "../src/identity"
import { UserID as UserIDUtil } from "../src/identity"

// This assignment should be REJECTED by TypeScript if UserID is truly branded.
// A plain string "user-123" must NOT be assignable to UserID without
// Schema.decodeSync or UserID.unsafe coercion.
const _plainString: UserID = "user-123" // <-- TS error expected here

// Valid paths: via Schema.decodeSync or .unsafe()
const _validViaUnsafe: UserID = UserIDUtil.unsafe("user-456")
