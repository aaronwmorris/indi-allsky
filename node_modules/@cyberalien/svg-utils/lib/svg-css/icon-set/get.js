import { findUsedKeyframes } from "../../css/find/animations.js";
import { findUsedClassNames } from "../../css/find/classname.js";
import { expandSVGCSSIconSetClass } from "./minify/expand.js";
function getSVGCSSIconFromIconSet(iconSet, name) {
	const fullName = iconSet.aliases?.[name] || name;
	const data = iconSet.icons[fullName];
	if (!data) return;
	const { viewBoxes, css, fallbackPrefix = "" } = iconSet;
	let viewBox = data.viewBox;
	if (typeof viewBox === "number") viewBox = viewBoxes?.[viewBox];
	if (!viewBox) return;
	let states = data.states;
	if (typeof states === "number") states = iconSet.statesList?.[states];
	const content = data.content;
	const classNames = findUsedClassNames(content);
	const classes = Object.create(null);
	const animations = Object.create(null);
	const statefulClasses = Object.create(null);
	const cssLines = [];
	classNames.forEach((className) => {
		const classContent = iconSet.classes?.[className];
		if (classContent) {
			if (css) expandSVGCSSIconSetClass(css, classContent);
			const { r, a, t, sr, st } = classContent;
			const statefulClass = Object.create(null);
			if (r) {
				classes[className] = r;
				cssLines.push(r);
			}
			if (a) {
				animations[className] = a;
				cssLines.push(a);
			}
			if (sr) {
				const stateRules = Object.create(null);
				statefulClass.stateRules = stateRules;
				for (const state in sr) {
					stateRules[state] = sr[state];
					cssLines.push(sr[state]);
				}
			}
			if (t) {
				statefulClass.transition = t;
				cssLines.push(t);
			}
			if (st) {
				const stateTransition = Object.create(null);
				statefulClass.stateTransition = stateTransition;
				for (const state in st) {
					stateTransition[state] = st[state];
					cssLines.push(st[state]);
				}
			}
			for (const key in statefulClass) {
				statefulClasses[className] = statefulClass;
				break;
			}
		}
	});
	const keyframes = Object.create(null);
	if (iconSet.keyframes) findUsedKeyframes(cssLines.join(";")).forEach((animationName) => {
		const keyframeContent = iconSet.keyframes[animationName];
		if (keyframeContent) keyframes[animationName] = keyframeContent;
	});
	const result = {
		content,
		viewBox,
		states,
		fallback: typeof data.fallback === "string" ? `${fallbackPrefix}${data.fallback}` : void 0
	};
	let _key;
	for (_key in classes) {
		result.classes = classes;
		break;
	}
	for (_key in animations) {
		result.animations = animations;
		break;
	}
	for (_key in keyframes) {
		result.keyframes = keyframes;
		break;
	}
	for (_key in statefulClasses) {
		result.statefulClasses = statefulClasses;
		break;
	}
	return result;
}
export { getSVGCSSIconFromIconSet };
