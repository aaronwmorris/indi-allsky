/**
* Minify viewBox by removing default values
*/
function minifyViewBox(viewBox) {
	const result = {
		width: viewBox.width,
		height: viewBox.height
	};
	if (viewBox.left) result.left = viewBox.left;
	if (viewBox.top) result.top = viewBox.top;
	if (viewBox.cx && viewBox.cx * 2 !== viewBox.width) result.cx = viewBox.cx;
	return result;
}
export { minifyViewBox };
