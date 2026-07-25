import { ParsedXMLNode, ParsedXMLTagElement } from "./types.js";
/**
 * Callback result
 *
 * - void: continue
 * - 'remove': remove current node
 * - 'skip': skip children
 * - 'abort': stop iteration
 */
type CallbackResult = void | 'remove' | 'skip' | 'abort';
declare function iterateXMLContent<T extends ParsedXMLTagElement | ParsedXMLNode>(root: T[], callback: (node: ParsedXMLNode, stack: ParsedXMLTagElement[]) => CallbackResult): T[];
export { iterateXMLContent };