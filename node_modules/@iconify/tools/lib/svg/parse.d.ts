import { SVG } from "./index.js";
import { ParsedXMLTagElement } from "@cyberalien/svg-utils";
/**
 * Item in callback
 */
interface ParseSVGCallbackItem {
  node: ParsedXMLTagElement;
  svg: SVG;
  parents: ParseSVGCallbackItem[];
  testChildren: boolean;
  removeNode: boolean;
}
/**
 * Callback function
 */
type ParseSVGCallback = (item: ParseSVGCallbackItem) => void;
/**
 * Parse SVG
 *
 * This function finds all elements in SVG and calls callback for each element.
 */
declare function parseSVG(svg: SVG, callback: ParseSVGCallback): void;
export { ParseSVGCallback, ParseSVGCallbackItem, parseSVG };