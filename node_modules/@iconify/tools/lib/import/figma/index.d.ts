import { DocumentNotModified } from "../../download/types/modified.js";
import { FigmaImportResult } from "./types/result.js";
import { FigmaIfModifiedSinceOption, FigmaImportOptions } from "./types/options.js";
/**
 * Import icon set from Figma
 */
declare function importFromFigma<T extends FigmaIfModifiedSinceOption & FigmaImportOptions>(options: T): Promise<FigmaImportResult | DocumentNotModified>;
declare function importFromFigma(options: FigmaImportOptions): Promise<FigmaImportResult>;
export { importFromFigma };