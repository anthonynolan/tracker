import { useRef, useState } from "react";
import type { DragEvent } from "react";
import { Box, Button, Paper, Typography } from "@mui/material";

interface Props {
  onFile: (file: File) => void;
  disabled?: boolean;
}

export default function Dropzone({ onFile, disabled }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function pick(files: FileList | null) {
    if (files && files.length > 0) onFile(files[0]);
  }

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    if (!disabled) pick(event.dataTransfer.files);
  }

  return (
    <Paper
      variant="outlined"
      sx={{ p: 4, textAlign: "center", borderStyle: "dashed" }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
    >
      <Typography variant="h6" gutterBottom>
        {dragging ? "Drop the video" : "Upload a video"}
      </Typography>
      <Typography variant="body2" color="text.secondary" gutterBottom>
        Drag a file here or choose one from disk.
      </Typography>
      <Box sx={{ mt: 2 }}>
        <Button
          variant="contained"
          disabled={disabled}
          onClick={() => inputRef.current?.click()}
        >
          Choose file
        </Button>
      </Box>
      <input
        ref={inputRef}
        type="file"
        accept="video/*"
        hidden
        onChange={(e) => {
          pick(e.target.files);
          e.target.value = "";
        }}
      />
    </Paper>
  );
}
