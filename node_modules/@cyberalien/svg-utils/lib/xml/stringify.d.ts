import { ParsedXMLNode, StringifyXMLOptions } from "./types.js";
/**
 * Convert parsed XML content to string
 */
declare function stringifyXMLContent(root: ParsedXMLNode[], options?: StringifyXMLOptions): string | null;
export { stringifyXMLContent };