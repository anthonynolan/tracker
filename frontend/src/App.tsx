import { useState } from "react";
import { Alert, Box, Container, LinearProgress, Stack, Typography } from "@mui/material";
import Dropzone from "./components/Dropzone";
import VideoPreview from "./components/VideoPreview";
import { uploadVideo } from "./api/client";
import type { UploadResponse } from "./api/client";

export default function App() {
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResponse | null>(null);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      setResult(await uploadVideo(file));
    } catch (err) {
      setError(err instanceof Error ? err.message : "upload failed");
    } finally {
      setUploading(false);
    }
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Box>
          <Typography variant="h4" component="h1" gutterBottom>
            Video Cropper
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Upload a video to inspect it. Tracking and cropping arrive in later phases.
          </Typography>
        </Box>
        <Dropzone onFile={handleFile} disabled={uploading} />
        {uploading && <LinearProgress />}
        {error && <Alert severity="error">{error}</Alert>}
        {result && !uploading && (
          <VideoPreview originalUrl={result.originalUrl} metadata={result.metadata} />
        )}
      </Stack>
    </Container>
  );
}
