import { useTheme } from "../theme";
import OpenCanvasMain from "./mains/OpenCanvasMain";
import SplitMain from "./mains/SplitMain";
import SignalMain from "./mains/SignalMain";

export default function MainPage() {
  const theme = useTheme();
  if (theme === "neon-studio" || theme === "analog-soul") return <SplitMain />;
  if (theme === "signal-lab") return <SignalMain />;
  return <OpenCanvasMain />;
}
