import { splitClassName } from "../../classname/toggle.js";
/**
* Find class names in content
*/
function findUsedClassNames(content) {
	const classNames = /* @__PURE__ */ new Set();
	content.matchAll(/class=["']([^"']+)["']/g).forEach((match) => {
		splitClassName(match[1]).forEach((className) => classNames.add(className));
	});
	return Array.from(classNames);
}
export { findUsedClassNames };
