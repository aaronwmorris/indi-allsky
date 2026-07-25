/**
* Clone object, maintaining types
*/
function cloneObject(item) {
	return JSON.parse(JSON.stringify(item));
}
export { cloneObject };
