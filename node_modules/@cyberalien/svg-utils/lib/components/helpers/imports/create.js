/**
* Create imports object
*/
function createFactoryImports() {
	return {
		default: Object.create(null),
		named: Object.create(null),
		types: Object.create(null),
		full: /* @__PURE__ */ new Set(),
		css: /* @__PURE__ */ new Set()
	};
}
export { createFactoryImports };
