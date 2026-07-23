import { createContext, useContext, type JSX } from "solid-js"

export type StudioPromptArtifact = { key: unknown; text: string }
export type StudioPromptContextValue = {
  peek: () => StudioPromptArtifact | undefined
  consume: (key: unknown) => void
}

const StudioPromptContext = createContext<StudioPromptContextValue>()

export function StudioPromptProvider(props: { value: StudioPromptContextValue; children: JSX.Element }) {
  return <StudioPromptContext.Provider value={props.value}>{props.children}</StudioPromptContext.Provider>
}

export function useStudioPromptContext() {
  return useContext(StudioPromptContext)
}
