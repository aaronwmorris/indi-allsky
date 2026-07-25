import { wrapSVGContent } from "../../svg/content/defs.js";
/**
* Normalise icon: apply transformations
*/
function normaliseIconifyIcon(data) {
	const viewBox = {
		left: data.left ?? 0,
		top: data.top ?? 0,
		width: data.width ?? 16,
		height: data.height ?? 16
	};
	let body = data.body;
	const transformations = [];
	let rotation = data.rotate ?? 0;
	if (data.hFlip) if (data.vFlip) rotation += 2;
	else {
		transformations.push("translate(" + (viewBox.width + viewBox.left).toString() + " " + (0 - viewBox.top).toString() + ")");
		transformations.push("scale(-1 1)");
		viewBox.top = viewBox.left = 0;
	}
	else if (data.vFlip) {
		transformations.push("translate(" + (0 - viewBox.left).toString() + " " + (viewBox.height + viewBox.top).toString() + ")");
		transformations.push("scale(1 -1)");
		viewBox.top = viewBox.left = 0;
	}
	if (rotation < 0) rotation -= Math.floor(rotation / 4) * 4;
	rotation = rotation % 4;
	switch (rotation) {
		case 1: {
			const value = viewBox.height / 2 + viewBox.top;
			transformations.unshift(`rotate(90 ${value} ${value})`);
			break;
		}
		case 2:
			transformations.unshift(`rotate(180 ${viewBox.width / 2 + viewBox.left} ${viewBox.height / 2 + viewBox.top})`);
			break;
		case 3: {
			const value = viewBox.width / 2 + viewBox.left;
			transformations.unshift(`rotate(-90 ${value} ${value})`);
			break;
		}
	}
	if (rotation % 2 === 1) {
		if (viewBox.left !== viewBox.top) {
			const tempValue = viewBox.left;
			viewBox.left = viewBox.top;
			viewBox.top = tempValue;
		}
		if (viewBox.width !== viewBox.height) {
			const tempValue = viewBox.width;
			viewBox.width = viewBox.height;
			viewBox.height = tempValue;
		}
	}
	if (transformations.length) body = wrapSVGContent(body, "<g transform=\"" + transformations.join(" ") + "\">", "</g>");
	return {
		body,
		viewBox
	};
}
export { normaliseIconifyIcon };
