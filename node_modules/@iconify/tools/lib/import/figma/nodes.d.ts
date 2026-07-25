import { FigmaDocument } from "./types/api.js";
import { FigmaNodesImportResult } from "./types/result.js";
import { FigmaGetIconNodesOptions } from "./types/options.js";
/**
 * Get node ids for icons
 */
declare function getFigmaIconNodes(document: FigmaDocument, options: FigmaGetIconNodesOptions): FigmaNodesImportResult;
export { getFigmaIconNodes };