import { ParsedXMLTagElement } from "../../xml/types.js";
import { ChangeIDResult } from "./types.js";
type HashCallback = (id: string, content: string, tagName: string) => string;
/**
 * Change IDs in SVG using a callback function
 */
declare function changeSVGIDs(root: ParsedXMLTagElement[], callback: HashCallback): ChangeIDResult;
export { changeSVGIDs };