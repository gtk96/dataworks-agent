import { Schema } from "effect"

// True branded UserID via Effect Schema.brand
// Schema.brand creates a nominal type at the TypeScript level
export const UserIDSchema = Schema.String.pipe(Schema.brand("UserID"))

// UserID type: inferred from the branded schema so the brand is preserved.
// Schema.Schema.Type<typeof UserIDSchema> yields `string & Brand<"UserID">`,
// which is NOT assignable from a plain string literal.
export type UserID = Schema.Schema.Type<typeof UserIDSchema>

// Runtime validators for the branded type
// Note: These use Schema.decodeSync/decodeUnknownSync which validate at runtime
export const UserID = {
  is: (u: unknown): u is UserID =>
    typeof u === "string" && Schema.decodeUnknownSync(UserIDSchema)(u) === u,

  unsafe: (s: string): UserID => {
    // decodeSync validates and returns the branded type
    const decoded = Schema.decodeSync(UserIDSchema)(s)
    // Cast to UserID - the brand provides type safety at the schema level
    return decoded as UserID
  },
}
