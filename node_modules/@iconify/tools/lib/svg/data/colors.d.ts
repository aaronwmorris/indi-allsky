/**
 * Check for color attribute
 */
declare function isSVGColorAttribute(prop: string): boolean;
/**
 * Check for color that cannot be parsed
 */
declare function isBadSVGColor(value: string): boolean;
export { isBadSVGColor, isSVGColorAttribute };