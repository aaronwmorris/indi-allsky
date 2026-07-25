/**
* Stringify properties
*/
function stringifyProps(props) {
	return Object.entries(props).map(([key, value]) => `${key}="${value}"`).join(" ");
}
export { stringifyProps };
