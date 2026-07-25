import { ParsedXMLTagElement } from "./types.js";
/**
 * Parse SVG content
 *
 * Returns null on error
 */
declare function parseXMLContent(content: string, trim?: boolean): ParsedXMLTagElement[] | null;
export { parseXMLContent };