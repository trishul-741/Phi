import { createRoot } from "react-dom/client";

import { OptionsApp } from "./OptionsApp";
import "../styles/base.css";

createRoot(document.getElementById("root") as HTMLElement).render(<OptionsApp />);
