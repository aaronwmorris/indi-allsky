import { ParsedXMLTagElement } from "../../xml/types.js";
import { UniqueIDOptions } from "./types.js";
/**
 * Create unique IDs for SVG elements
 */
declare function createUniqueIDs(root: ParsedXMLTagElement[], options: UniqueIDOptions): void;
export { createUniqueIDs };