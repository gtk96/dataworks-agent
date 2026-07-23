/** Ambient declarations for optional heavy knowledge dependencies. */
declare module "pdf-parse" {
  const pdfParse: (data: Buffer) => Promise<{ text: string; numpages?: number }>
  export default pdfParse
}

declare module "mammoth" {
  export function extractRawText(input: { buffer: Buffer }): Promise<{ value: string }>
}

declare module "fastembed" {
  export const EmbeddingModel: { MLE5Large: unknown }
  export const FlagEmbedding: {
    init: (opts: Record<string, unknown>) => Promise<{
      passageEmbed: (texts: string[], batch?: number) => AsyncGenerator<number[][], void, unknown> | Promise<number[][]>
      queryEmbed: (text: string) => Promise<number[]> | AsyncGenerator<number[], void, unknown>
    }>
  }
}

declare module "@lancedb/lancedb" {
  export function connect(uri: string): Promise<unknown>
}
