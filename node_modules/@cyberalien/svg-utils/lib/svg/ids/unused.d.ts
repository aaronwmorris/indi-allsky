import { ParsedXMLTagElement } from "../../xml/types.js";
import { ChangeIDResult } from "./types.js";
/**
 * Remove duplicate IDs from SVG
 */
declare function removeUnusedIDs(root: ParsedXMLTagElement[], data: ChangeIDResult): ParsedXMLTagElement[];
export { removeUnusedIDs };