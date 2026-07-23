import type { DataWorksProject } from "@/context/dataworks"

export function projectKey(project: DataWorksProject): string {
  const candidates = [project.projectId, project.id]
  for (const value of candidates) {
    if (value !== undefined && value !== null && value !== "") return String(value)
  }
  return ""
}

export function projectLabel(project: DataWorksProject): string {
  const id = projectKey(project)
  const name =
    typeof project.projectName === "string" && project.projectName.trim()
      ? project.projectName
      : typeof project.name === "string" && project.name.trim()
        ? project.name
        : undefined
  if (name && id && name !== id) return `${name} (${id})`
  if (name) return name
  if (id) return id
  return "project"
}
