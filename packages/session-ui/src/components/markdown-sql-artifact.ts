const sqlLanguages = new Set(["sql", "odps", "maxcompute"])

export function shouldShowSqlArtifactButton(language: string | undefined, complete: boolean, sql = "") {
  return complete && sql.length <= 4000 && sqlLanguages.has(language?.toLowerCase() ?? "")
}
