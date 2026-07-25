import { FactoryComponentProps } from "./types.js";
/**
 * Stringify properties for component
 */
declare function stringifyFactoryPropTypes(props: FactoryComponentProps): string;
/**
 * Get used properties
 */
declare function getUsedFactoryProps(props: FactoryComponentProps): string[];
export { getUsedFactoryProps, stringifyFactoryPropTypes };