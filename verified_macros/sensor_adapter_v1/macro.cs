using System;
using TFlex;
using TFlex.Model;
using TFlex.Model.Model2D;
using TFlex.Model.Model3D;

namespace PoleSocketComplete
{
    public class Macro
    {
        public static void Run()
        {
            Document doc = Application.ActiveDocument;
            if (doc == null) return;
            bool editing = false;
            string step = "Проверка документа";
            try
            {
                if (doc.GetObjectByName("PS 01 Наружный цилиндр") != null)
                    throw new InvalidOperationException("В документе уже есть PS 01. Запустите макрос в новом пустом 3D-документе.");
                doc.BeginChanges("01_Pole_socket — полное построение");
                editing = true;
                step = "Переменные";
                foreach (Dimension item in GetDimensions())
                {
                    string name = "PS_" + item.Name;
                    Variable variable = doc.FindVariable(name);
                    if (variable == null) variable = new Variable(doc, name, item.Value);
                    else
                    {
                        if (!variable.IsReal) throw new InvalidOperationException("Не числовая переменная: " + name);
                        variable.RealValue = item.Value;
                    }
                    variable.Comment = item.Comment;
                }

                step = "Основные примитивы";
                Cylinder shell = AddCylinder(doc, "PS 01 Наружный цилиндр", 28.4, 40.0);
                Block bridge = AddBlock(doc, "PS 02 Перемычка", 24.0, 23.0, 40.0);
                Block receiver = AddBlock(doc, "PS 03 Приёмник", 36.1, 18.0, 40.0);
                Cylinder cavity = AddCylinder(doc, "PS 04 Инструмент гнезда трубы", 19.4, 38.0);
                Cylinder bolt = AddCylinder(doc, "PS 05 Инструмент отверстия под болт", 4.0, 44.1);
                Cylinder pin = AddCylinder(doc, "PS 06 Инструмент отверстия под штифт", 4.3, 42.1);
                Cylinder cable = AddCylinder(doc, "PS 07 Инструмент кабельного канала", 5.5, 44.0);
                Block cableExit = AddBlock(doc, "PS 08 Инструмент бокового выхода кабеля", 5.5, 16.5, 44.0);

                step = "Расстановка примитивов";
                Place(shell, 0, 0, 0, false);
                Place(bridge, 0, 11.5, 0, false);
                Place(receiver, 0, 23.0, 0, false);
                Place(cavity, 0, 0, 3.0, false);
                PlaceHole(bolt, 0, 0, 14.0);
                PlaceHole(pin, 0, 26.5, 10.0);
                Place(cable, 0, 18.5, 0, false);
                Place(cableExit, 0, 26.75, 0, false);

                step = "Шесть вершин ласточкиного хвоста";
                double[] x = { -10, 10, 7, 7, -7, -7 };
                // Координаты профиля на плоскости Top имеют противоположное направление Y
                // относительно размещения 3D-примитивов (проверено по виду сверху в v5).
                double[] y = { -22, -22, -32, -35, -35, -32 };
                FreeNode[] nodes = new FreeNode[6];
                SegmentOutline[] edges = new SegmentOutline[6];
                for (int i = 0; i < 6; i++)
                    nodes[i] = new FreeNode(doc, new Parameter(x[i]), new Parameter(y[i]));
                for (int i = 0; i < 6; i++)
                    edges[i] = new SegmentOutline(doc, nodes[i], nodes[(i + 1) % 6]);
                Area area = new Area(doc);
                TFlex.Model.Model2D.Contour contour = area.AppendContour();
                for (int i = 0; i < 6; i++)
                {
                    OutlineContourSegment segment = new OutlineContourSegment(contour);
                    segment.Outline = edges[i];
                    segment.Direction = true;
                }
                StandardWorkplane plane = new StandardWorkplane(doc, StandardWorkplane.StandardType.Top);
                AreaProfile profile = new AreaProfile(doc);
                profile.Area = area;
                profile.WorkSurface = plane;
                ThickenExtrusion dovetail = new ThickenExtrusion(doc);
                dovetail.Name = "PS 09 Инструмент ласточкиного хвоста";
                dovetail.Thickness1 = new Parameter(0.0);
                dovetail.LengthType = ThickenExtrusion.LengthValue.ValueValue;
                dovetail.ForwardLength = new Parameter(38.0);
                dovetail.Profile.Add(profile.Geometry.SheetContour);
                // Калибровка по фактическим результатам T-FLEX 17:
                // при Z=-22 инструмент пересекает нижние 16 мм корпуса,
                // при Z=+16 — верхние 24 мм. Это соответствует диапазону
                // выталкивания [Z-20, Z+18] (длина 38 мм).
                // При Z=-2 диапазон инструмента будет [-22, +16],
                // а паз внутри корпуса — [-20, +16], глубина 36 мм.
                Place(dovetail, 0, 0, -2, false);

                step = "Булевы операции";
                Operation body = shell;
                body = Apply(doc, "01 Объединение перемычки", "Unite", body, bridge);
                body = Apply(doc, "02 Объединение приёмника", "Unite", body, receiver);
                body = Apply(doc, "03 Гнездо трубы", "Subtract", body, cavity);
                body = Apply(doc, "04 Ласточкин хвост", "Subtract", body, dovetail);
                body = Apply(doc, "05 Отверстие под болт", "Subtract", body, bolt);
                body = Apply(doc, "06 Отверстие под штифт", "Subtract", body, pin);
                body = Apply(doc, "07 Кабельный канал", "Subtract", body, cable);
                body = Apply(doc, "08 Боковой выход кабеля", "Subtract", body, cableExit);
                doc.EndChanges();
                editing = false;
                step = "Пересчёт 3D модели";
                doc.Regenerate(new RegenerateOptions());
                if (body.Body == null || body.Geometry == null)
                    throw new InvalidOperationException("Итоговое тело не сформировано. Проверьте диагностику операций.");
            }
            catch (Exception ex)
            {
                if (editing) doc.CancelChanges();
                doc.Diagnostics.Add(new DiagnosticsMessage(DiagnosticsMessageType.Error,
                    "01_Pole_socket — " + step + ": " + ex.GetBaseException().Message));
            }
        }

        private static Cylinder AddCylinder(Document doc, string name, double diameter, double height)
        {
            Cylinder item = new Cylinder(doc);
            item.Name = name;
            item.Symmetry = false;
            item.Diameter = new Parameter(diameter);
            item.Height = new Parameter(height);
            return item;
        }
        private static Block AddBlock(Document doc, string name, double x, double y, double z)
        {
            Block item = new Block(doc);
            item.Name = name;
            item.Cube = false;
            item.Symmetry = false;
            item.XSize = new Parameter(x);
            item.YSize = new Parameter(y);
            item.ZSize = new Parameter(z);
            return item;
        }
        private static void Place(Object3D obj, double x, double y, double z, bool rotateToX)
        {
            TransformationGroupContainer transforms = obj.Transformations;
            transforms.DeleteAllBaseTransfGroups();
            TransformationGroupBase group = transforms.AddBaseTransfGroup();
            if (rotateToX) group.AddRotateTransf(TransformationCoordinate.Y, new Parameter(90.0));
            if (x != 0) group.AddMoveTransf(TransformationCoordinate.X, new Parameter(x));
            if (y != 0) group.AddMoveTransf(TransformationCoordinate.Y, new Parameter(y));
            if (z != 0) group.AddMoveTransf(TransformationCoordinate.Z, new Parameter(z));
        }
        // Порядок "перенос, затем поворот" подтверждён тестом 06 C.
        // Для обоих горизонтальных инструментов используем одинаковую схему.
        private static void PlaceHole(Object3D obj, double x, double y, double z)
        {
            TransformationGroupContainer transforms = obj.Transformations;
            transforms.DeleteAllBaseTransfGroups();
            TransformationGroupBase group = transforms.AddBaseTransfGroup();
            if (x != 0) group.AddMoveTransf(TransformationCoordinate.X, new Parameter(x));
            if (y != 0) group.AddMoveTransf(TransformationCoordinate.Y, new Parameter(y));
            if (z != 0) group.AddMoveTransf(TransformationCoordinate.Z, new Parameter(z));
            group.AddRotateTransf(TransformationCoordinate.Y, new Parameter(90.0));
        }

        private static Operation Apply(Document doc, string name, string function,
            Operation first, Operation second)
        {
            BooleanOperation result = new BooleanOperation(doc);
            result.Name = "PS Boolean — " + name;
            result.Function = function == "Unite"
                ? BooleanOperation.FunctionType.Unite
                : BooleanOperation.FunctionType.Subtract;
            result.FirstOperands.Add(new BooleanOperation.OperandsArray.Operand(first, false));
            result.SecondOperands.Add(new BooleanOperation.OperandsArray.Operand(second, false));
            return result;
        }

        private static Dimension[] GetDimensions()
        {
            // Все линейные размеры и координаты — в мм.
            const double tubeOD = 19.0;
            const double tubeClearance = 0.40;
            const double wall = 4.5;
            const double floor = 4.0;
            const double bottom = -20.0;
            const double top = 20.0;

            const double bridgeHalf = 12.0;
            const double bridgeY0 = 0.0;
            const double bridgeY1 = 23.0;
            const double receiverBack = 14.0;
            const double receiverFront = 32.0;

            const double bossWidth = 14.3;
            const double insertBase = 2.0;
            const double toothDepth = 0.70;
            const double forkClearance = 0.40;
            const double ear = 8.0;

            const double dovetailBack = 22.0;
            const double dovetailWideHalf = 10.0;
            const double dovetailNeckHalf = 7.0;
            const double dovetailStop = 16.0;

            const double boltD = 4.0;
            const double boltHeight = 30.0;
            const double pinD = 4.0;
            const double pinClearance = 0.30;
            const double pinY = 26.5;
            const double pinZ = 10.0;
            const double cableD = 5.5;
            const double cableX = 0.0;
            const double cableY = 18.5;

            const double cutZExtra = 2.0;
            const double cutYExtra = 3.0;
            const double boltExtra = 8.0;
            const double pinExtra = 6.0;

            double innerD = tubeOD + tubeClearance;
            double outerD = innerD + 2.0 * wall;
            double height = top - bottom;
            double width = bossWidth + 2.0 * (insertBase + toothDepth)
                           + forkClearance + 2.0 * ear;
            double bridgeX = 2.0 * bridgeHalf;

            return new Dimension[]
            {
                new Dimension("TubeOD", tubeOD, "Наружный диаметр трубы"),
                new Dimension("TubeClearance", tubeClearance, "Диаметральный зазор трубы"),
                new Dimension("Wall", wall, "Толщина стенки обоймы"),
                new Dimension("Floor", floor, "Толщина дна гнезда"),
                new Dimension("Bottom", bottom, "Нижняя плоскость корпуса, Z"),
                new Dimension("Top", top, "Верхняя плоскость корпуса, Z"),

                new Dimension("BridgeHalf", bridgeHalf, "Половина ширины перемычки"),
                new Dimension("BridgeY0", bridgeY0, "Начало перемычки, Y"),
                new Dimension("BridgeY1", bridgeY1, "Конец перемычки, Y"),
                new Dimension("ReceiverBack", receiverBack, "Задняя грань приёмника, Y"),
                new Dimension("ReceiverFront", receiverFront, "Передняя грань приёмника, Y"),

                new Dimension("BossWidth", bossWidth, "Ширина проушины датчика"),
                new Dimension("InsertBase", insertBase, "Толщина основания вставки"),
                new Dimension("ToothDepth", toothDepth, "Глубина зубьев вставки"),
                new Dimension("ForkClearance", forkClearance, "Осевой зазор вилки"),
                new Dimension("EarThickness", ear, "Толщина одного уха вилки"),

                new Dimension("DovetailBack", dovetailBack, "Задняя стенка паза, Y"),
                new Dimension("DovetailWideHalf", dovetailWideHalf, "Половина ширины паза в глубине"),
                new Dimension("DovetailNeckHalf", dovetailNeckHalf, "Половина ширины входа паза"),
                new Dimension("DovetailStop", dovetailStop, "Верхний упор паза, Z"),

                new Dimension("BoltD", boltD, "Диаметр отверстия под болт трубы"),
                new Dimension("BoltHeight", boltHeight, "Высота оси болта от дна гнезда"),
                new Dimension("PinD", pinD, "Номинальный диаметр штифта"),
                new Dimension("PinClearance", pinClearance, "Диаметральный зазор штифта"),
                new Dimension("PinY", pinY, "Координата оси штифта, Y"),
                new Dimension("PinZ", pinZ, "Координата оси штифта, Z"),
                new Dimension("CableD", cableD, "Диаметр кабельного канала"),
                new Dimension("CableX", cableX, "Ось кабельного канала, X"),
                new Dimension("CableY", cableY, "Ось кабельного канала, Y"),

                new Dimension("CutZExtra", cutZExtra, "Запас режущего тела по Z"),
                new Dimension("CutYExtra", cutYExtra, "Запас режущего тела спереди по Y"),
                new Dimension("BoltExtra", boltExtra, "Запас длины инструмента отверстия под болт"),
                new Dimension("PinExtra", pinExtra, "Запас длины инструмента отверстия под штифт"),

                new Dimension("InnerD", innerD, "Диаметр гнезда трубы"),
                new Dimension("OuterD", outerD, "Наружный диаметр обоймы"),
                new Dimension("Height", height, "Высота корпуса"),
                new Dimension("Width", width, "Ширина приёмника"),
                new Dimension("BridgeX", bridgeX, "Ширина перемычки по X"),
                new Dimension("BridgeY", bridgeY1 - bridgeY0, "Длина перемычки по Y"),
                new Dimension("ReceiverY", receiverFront - receiverBack, "Глубина приёмника по Y"),
                new Dimension("SocketDepth", height - floor, "Глубина гнезда трубы"),
                new Dimension("CavityH", height - floor + cutZExtra, "Высота инструмента гнезда"),
                new Dimension("CutH", height + 2.0 * cutZExtra, "Высота инструмента кабельного канала"),
                new Dimension("BoltL", Math.Max(outerD, Math.Max(bridgeX, width)) + boltExtra,
                    "Длина инструмента отверстия под болт"),
                new Dimension("BoltZ", bottom + floor + boltHeight, "Координата оси болта, Z"),
                new Dimension("PinL", width + pinExtra, "Длина инструмента отверстия под штифт"),
                new Dimension("PinHoleD", pinD + pinClearance, "Диаметр отверстия под штифт"),
                new Dimension("CableExitY", receiverFront + cutYExtra - cableY,
                    "Длина бокового выхода кабельного канала по Y"),
                new Dimension("DovetailH", dovetailStop - bottom + cutZExtra,
                    "Высота инструмента выреза паза")
            };
        }

        private sealed class Dimension
        {
            public readonly string Name;
            public readonly double Value;
            public readonly string Comment;

            public Dimension(string name, double value, string comment)
            {
                Name = name;
                Value = value;
                Comment = comment;
            }
        }
    }
}