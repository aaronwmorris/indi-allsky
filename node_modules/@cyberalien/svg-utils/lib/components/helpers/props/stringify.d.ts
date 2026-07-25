import { FactoryComponentProps } from "./types.js";
/**
 * Template for property
 */
declare const factoryPropTemplate = "{prop}=\"{value}\"";
/**
 * Stringify properties for component
 */
declare function stringifyFactoryProps(props: FactoryComponentProps, dynamicTemplate: string, staticTemplate?: string, separator?: string): string;
export { factoryPropTemplate, stringifyFactoryProps };