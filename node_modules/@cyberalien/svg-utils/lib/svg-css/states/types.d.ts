/**
 * States for stateful icons
 */
type IconStatesSimpleState = Readonly<string>;
type IconStatesAdvancedStateValues = string[] | Readonly<string[]>;
type IconStatesAdvancedState = Readonly<[string, IconStatesAdvancedStateValues] | [string, IconStatesAdvancedStateValues, string]>;
type IconStatesState = IconStatesSimpleState | IconStatesAdvancedState;
type IconStatesList = IconStatesState[];
export { IconStatesAdvancedState, IconStatesAdvancedStateValues, IconStatesList, IconStatesSimpleState, IconStatesState };