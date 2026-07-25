import { calculateSize } from "../../../svg/props/size.js";
/**
* Get size values for component
*/
function getComponentSizeValues(options, viewBox) {
	const { width, height, square } = options;
	if (width && height) return {
		width,
		height
	};
	if (height) return {
		width: square ? height : calculateSize(height, viewBox.width / viewBox.height),
		height
	};
	if (width) return {
		width,
		height: square ? width : calculateSize(width, viewBox.height / viewBox.width)
	};
}
export { getComponentSizeValues };
