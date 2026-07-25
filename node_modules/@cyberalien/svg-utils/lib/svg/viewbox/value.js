/**
* Convert IconViewBox to string
*/
function stringifyIconViewBox(viewBox) {
	return `${viewBox.left ?? 0} ${viewBox.top ?? 0} ${viewBox.width} ${viewBox.height}`;
}
export { stringifyIconViewBox };
