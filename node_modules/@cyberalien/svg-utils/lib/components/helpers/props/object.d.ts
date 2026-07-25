import { FactoryComponentProps } from "./types.js";
/**
 * Stringify properties for component as JS object
 */
declare function stringifyFactoryPropsAsJSON(props: FactoryComponentProps, separator?: string): string;
export { stringifyFactoryPropsAsJSON };