from django.db import models


class UploadedFile(models.Model):
    UPLOAD_TYPE_CHOICES = [
        ('manual', 'Manual Upload'),
        ('automatic', 'Automatic Upload'),
        ('api', 'API Upload'),
        ('resume', 'Resume Upload'),
    ]

    file = models.FileField(upload_to='uploads/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    upload_type = models.CharField(max_length=20, choices=UPLOAD_TYPE_CHOICES, default='manual')
    def __str__(self):
        return f"{self.file.name} ({self.upload_type})"

# Create your models here.
class Product(models.Model):
    name = models.CharField(max_length=255)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    description = models.TextField()

    def __str__(self):
        return self.name