/**
* Make viewBox square
*/
function makeSquareViewBox(viewBox) {
	const { width, height } = viewBox;
	if (width === height) return { ...viewBox };
	if (width >= height) {
		const diff = (width - height) / 2;
		return {
			left: viewBox.left,
			top: (viewBox.top ?? 0) - diff,
			width,
			height: width
		};
	}
	return {
		left: (viewBox.cx ?? width / 2 + (viewBox.left ?? 0)) - height / 2,
		top: viewBox.top,
		width: height,
		height
	};
}
export { makeSquareViewBox };
