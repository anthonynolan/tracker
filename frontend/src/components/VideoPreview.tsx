import { Box, Stack, Typography } from "@mui/material";
import type { VideoMetadata } from "../api/client";

interface Props {
  originalUrl: string;
  metadata: VideoMetadata;
}

export default function VideoPreview({ originalUrl, metadata }: Props) {
  const rows: Array<[string, string]> = [
    ["File", metadata.filename],
    ["Size", `${metadata.width} x ${metadata.height}`],
    ["FPS", metadata.fps.toFixed(2)],
    ["Duration", `${metadata.duration.toFixed(2)} s`],
    ["Frames", String(metadata.totalFrames)],
    ["Video ID", metadata.videoId],
  ];
  return (
    <Stack spacing={2}>
      <Box
        component="video"
        src={originalUrl}
        controls
        sx={{ width: "100%", maxHeight: 480, backgroundColor: "black" }}
      />
      <Box component="dl" sx={{ display: "grid", gridTemplateColumns: "120px 1fr", rowGap: 0.5, m: 0 }}>
        {rows.map(([term, value]) => (
          <Box key={term} sx={{ display: "contents" }}>
            <Typography component="dt" variant="body2" color="text.secondary">
              {term}
            </Typography>
            <Typography component="dd" variant="body2" sx={{ m: 0, overflowWrap: "anywhere" }}>
              {value}
            </Typography>
          </Box>
        ))}
      </Box>
    </Stack>
  );
}
