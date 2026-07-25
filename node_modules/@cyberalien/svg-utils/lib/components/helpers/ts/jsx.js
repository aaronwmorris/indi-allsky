import { addComponentTypes, omitComponentSVGProps } from "./wrapper.js";
const iconPropsTemplate = `interface IconProps {
/* PROPS */
}`;
const exportTemplate = `export { type IconProps };
export default Component;`;
/**
* Add JSX component types
*/
function addJSXComponentTypes(data, options, assets, props) {
	let template;
	switch (options.jsx) {
		case "react":
			template = `import type { ForwardRefExoticComponent, SVGProps } from 'react';

${iconPropsTemplate}

const Component: ForwardRefExoticComponent<
    Omit<SVGProps<SVGSVGElement>, ${omitComponentSVGProps}> & IconProps
>;

${exportTemplate}
`;
			break;
		case "preact": template = `import type { JSX } from 'preact';

${iconPropsTemplate}

const Component: (props: Omit<JSX.SVGAttributes<SVGSVGElement>, ${omitComponentSVGProps}> & IconProps) => JSX.Element;

${exportTemplate}
`;
	}
	return addComponentTypes(template, data, options, assets, props);
}
export { addJSXComponentTypes };
