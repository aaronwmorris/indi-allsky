import { runSVGO } from "./svgo.js";

/**
* Reset origin to 0 0
*/
function resetSVGOrigin(svg) {
	const viewBox = svg.viewBox;
	const left = viewBox.left ?? 0;
	const top = viewBox.top ?? 0;
	if (left || top) {
		const content = `<svg width="${viewBox.width}" height="${viewBox.height}" viewBox="0 0 ${viewBox.width} ${viewBox.height}"><g transform="translate(${0 - left} ${0 - top})">${svg.getBody()}</g></svg>`;
		svg.load(content);
		runSVGO(svg, { plugins: [
			"collapseGroups",
			"convertTransform",
			"convertPathData",
			"sortAttrs"
		] });
	}
}

export { resetSVGOrigin };