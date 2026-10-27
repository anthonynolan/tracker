import { Box, Stack, Typography } from "@mui/material";
import type { BBox } from "../api/client";

export interface StripItem {
  frameIdx: number;
  url: string;
  bbox: BBox | null;
}

export default function KeyframeStrip({ items }: { items: StripItem[] }) {
  return (
    <Box sx={{ overflowX: "auto" }}>
      <Stack direction="row" spacing={2} sx={{ minWidth: "max-content", py: 1 }}>
        {items.map((item) => (
          <Box key={item.frameIdx} sx={{ width: 220 }}>
            <Box sx={{ position: "relative", width: 220, backgroundColor: "black" }}>
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
            </Box>
            <Typography variant="caption" color="text.secondary">
              frame {item.frameIdx}
              {item.bbox ? "" : " (no detection)"}
            </Typography>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
