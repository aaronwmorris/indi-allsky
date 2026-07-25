import { stringifyFactoryProps } from "./stringify.js";
/**
* Stringify properties for component as JS object
*/
function stringifyFactoryPropsAsJSON(props, separator = "\n	") {
	return stringifyFactoryProps(props, "\"{prop}\": {value},", "\"{prop}\": \"{value}\",", separator);
}
export { stringifyFactoryPropsAsJSON };
