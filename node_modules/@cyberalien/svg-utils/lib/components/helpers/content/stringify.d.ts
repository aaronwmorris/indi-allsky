import { CSSGeneratedStylesheet } from "../../../css/types.js";
import { ComponentFactorySource } from "../../types/source.js";
/**
 * Convert icon content to a string literal
 */
declare function stringifyFactoryIconContent(icon: Omit<ComponentFactorySource, 'viewBox' | 'fallback' | 'states'>, embedCSS?: CSSGeneratedStylesheet, addQuotes?: boolean): string;
export { stringifyFactoryIconContent };