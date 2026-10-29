import { Box, Button, Checkbox, Stack, Typography } from "@mui/material";
import type { BBox } from "../api/client";

export interface GridItem {
  frameIdx: number;
  url: string;
  bbox: BBox | null;
  origin: string;
}

interface Props {
  items: GridItem[];
  selected: number[];
  onToggle: (frameIdx: number) => void;
  onSelectAll: () => void;
  onClear: () => void;
  disabled?: boolean;
}

export default function KeyframeGrid({
  items, selected, onToggle, onSelectAll, onClear, disabled,
}: Props) {
  const all = items.length > 0 && selected.length === items.length;
  return (
    <Stack spacing={1}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
        <Typography variant="subtitle1" sx={{ flexGrow: 1 }}>
          {items.length} keyframes
          {selected.length > 0 ? ` — ${selected.length} selected` : ""}
        </Typography>
        <Button size="small" onClick={onSelectAll} disabled={disabled || all}>
          Select all
        </Button>
        <Button size="small" onClick={onClear} disabled={disabled || selected.length === 0}>
          Clear
        </Button>
      </Stack>
      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
          gap: 2,
        }}
      >
        {items.map((item) => {
          const checked = selected.includes(item.frameIdx);
          return (
            <Box
              key={item.frameIdx}
              onClick={() => {
                if (!disabled) onToggle(item.frameIdx);
              }}
              sx={{
                position: "relative",
                backgroundColor: "black",
                cursor: disabled ? "default" : "pointer",
                outline: checked ? "2px solid" : "none",
                outlineColor: "primary.main",
              }}
            >
              <Box
                component="img"
                src={item.url}
                alt={`frame ${item.frameIdx}`}
                sx={{ display: "block", width: "100%" }}
              />
              {item.bbox && (
                <Box
                  sx={{
                    position: "absolute",
                    left: `${item.bbox.x * 100}%`,
                    top: `${item.bbox.y * 100}%`,
                    width: `${item.bbox.w * 100}%`,
                    height: `${item.bbox.h * 100}%`,
                    border: "2px solid red",
                    boxSizing: "border-box",
                  }}
                />
              )}
              <Checkbox
                checked={checked}
                disabled={disabled}
                onClick={(e) => e.stopPropagation()}
                onChange={() => onToggle(item.frameIdx)}
                size="small"
                sx={{
                  position: "absolute",
                  top: 0,
                  left: 0,
                  color: "white",
                  "&.Mui-checked": { color: "primary.main" },
                }}
              />
              <Box
                sx={{
                  position: "absolute",
                  bottom: 0,
                  left: 0,
                  right: 0,
                  backgroundColor: "rgba(0,0,0,0.6)",
                  px: 1,
                }}
              >
                <Typography variant="caption" sx={{ color: "white" }}>
                  frame {item.frameIdx}
                  {item.origin === "fix" ? " (fix)" : ""}
                  {item.bbox ? "" : " — no detection"}
                </Typography>
              </Box>
            </Box>
          );
        })}
      </Box>
    </Stack>
  );
}
