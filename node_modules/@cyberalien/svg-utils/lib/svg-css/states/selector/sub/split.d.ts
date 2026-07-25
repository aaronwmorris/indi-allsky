import { StateSelectorSubParts } from "../types.js";
declare const combinators: Set<string>;
/**
 * Split selector into smaller parts
 *
 * Assuming selector is in format: '.foo[bar="baz"]:hover:active'
 * Class name should be before attribute selector, pseudo-classes should be last
 */
declare function splitSelectorToSubParts(selector: string): StateSelectorSubParts;
export { combinators, splitSelectorToSubParts };