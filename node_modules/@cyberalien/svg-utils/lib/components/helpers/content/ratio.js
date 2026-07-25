/**
* Get viewBox ratio as string
*/
function getViewBoxRatio(viewBox) {
	const ratio = viewBox.width / viewBox.height;
	return (Math.ceil(ratio * 100) / 100).toFixed(2).replace(/\.?0+$/, "");
}
export { getViewBoxRatio };
