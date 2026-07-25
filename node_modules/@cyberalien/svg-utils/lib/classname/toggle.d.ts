/**
 * Split class name by spaces
 */
declare function splitClassName(className: string): string[];
/**
 * Add/remove class name
 */
declare function toggleClassName(attribs: Record<string, unknown>, className: string, add: boolean, prop?: string): void;
export { splitClassName, toggleClassName };