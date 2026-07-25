/**
 * Tag
 */
interface ParsedXMLTagElement {
  type: 'tag';
  tag: string;
  attribs: Record<string, string | number>;
  children: ParsedXMLNode[];
}
/**
 * Text
 */
interface ParsedXMLTextElement {
  type: 'text';
  content: string;
}
/**
 * Element in tree
 */
type ParsedXMLNode = ParsedXMLTagElement | ParsedXMLTextElement;
/**
 * Options for stringifying XML
 */
interface StringifyXMLOptions {
  useSelfClosing?: boolean;
  numberTemplate?: string;
  prettyPrint?: boolean | string;
}
export { ParsedXMLNode, ParsedXMLTagElement, ParsedXMLTextElement, StringifyXMLOptions };