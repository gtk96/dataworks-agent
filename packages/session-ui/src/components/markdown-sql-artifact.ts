const sqlLanguages = new Set(["sql", "odps", "maxcompute"])

export function shouldShowSqlArtifactButton(language: string | undefined, complete: boolean) {
  return complete && sqlLanguages.has(language?.toLowerCase() ?? "")
}
