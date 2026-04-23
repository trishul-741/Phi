import { createRoot } from "react-dom/client";

import { PopupApp } from "./PopupApp";
import "../styles/base.css";

createRoot(document.getElementById("root") as HTMLElement).render(<PopupApp />);
