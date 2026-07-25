import { StateSelectorParts } from "../types.js";
/**
 * Create selector parts from given parameters
 *
 * Should be used when selector is hard to parse from string, such as:
 * - `@media (max-width: 600px) label:focus &` -> parser will not be able to tell if "label" is part of at-rule or parent selector
 */
declare function createSelectorParts(atRules: string[] | null, parentSelectors: string | string[] | null, svgSelector: string | null): StateSelectorParts;
/**
 * Split selector into parts
 */
declare function splitSelectorToParts(selector: string): StateSelectorParts | null;
export { createSelectorParts, splitSelectorToParts };